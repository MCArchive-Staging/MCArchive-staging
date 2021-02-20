package io.papermc.hangar.service.internal.versions;

import io.papermc.hangar.db.customtypes.LoggedActionType;
import io.papermc.hangar.db.customtypes.LoggedActionType.VersionContext;
import io.papermc.hangar.db.dao.HangarDao;
import io.papermc.hangar.db.dao.internal.table.PlatformVersionDAO;
import io.papermc.hangar.db.dao.internal.table.versions.ProjectVersionDependenciesDAO;
import io.papermc.hangar.db.dao.internal.table.versions.ProjectVersionPlatformDependenciesDAO;
import io.papermc.hangar.db.dao.internal.table.versions.ProjectVersionsDAO;
import io.papermc.hangar.exceptions.HangarApiException;
import io.papermc.hangar.model.api.project.version.FileInfo;
import io.papermc.hangar.model.api.project.version.PluginDependency;
import io.papermc.hangar.model.common.Platform;
import io.papermc.hangar.model.common.projects.Visibility;
import io.papermc.hangar.model.db.PlatformVersionTable;
import io.papermc.hangar.model.db.projects.ProjectChannelTable;
import io.papermc.hangar.model.db.projects.ProjectTable;
import io.papermc.hangar.model.db.versions.ProjectVersionDependencyTable;
import io.papermc.hangar.model.db.versions.ProjectVersionPlatformDependencyTable;
import io.papermc.hangar.model.db.versions.ProjectVersionTable;
import io.papermc.hangar.model.db.versions.ProjectVersionTagTable;
import io.papermc.hangar.model.internal.versions.PendingVersion;
import io.papermc.hangar.service.HangarService;
import io.papermc.hangar.service.VisibilityService.ProjectVisibilityService;
import io.papermc.hangar.service.api.UsersApiService;
import io.papermc.hangar.service.internal.projects.ChannelService;
import io.papermc.hangar.service.internal.projects.PlatformService;
import io.papermc.hangar.service.internal.projects.ProjectService;
import io.papermc.hangar.service.internal.uploads.ProjectFiles;
import io.papermc.hangar.service.internal.users.NotificationService;
import io.papermc.hangar.service.internal.versions.plugindata.PluginFileWithData;
import io.papermc.hangar.util.CryptoUtils;
import io.papermc.hangar.util.StringUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.Objects;

@Service
public class VersionFactory extends HangarService {

    private final ProjectVersionPlatformDependenciesDAO projectVersionPlatformDependenciesDAO;
    private final ProjectVersionDependenciesDAO projectVersionDependenciesDAO;
    private final PlatformVersionDAO platformVersionDAO;
    private final ProjectVersionsDAO projectVersionsDAO;
    private final ProjectFiles projectFiles;
    private final PluginDataService pluginDataService;
    private final ChannelService channelService;
    private final ProjectVisibilityService projectVisibilityService;
    private final RecommendedVersionService recommendedVersionService;
    private final ProjectService projectService;
    private final NotificationService notificationService;
    private final VersionService versionService;
    private final PlatformService platformService;
    private final UsersApiService usersApiService;

    @Autowired
    public VersionFactory(HangarDao<ProjectVersionPlatformDependenciesDAO> projectVersionPlatformDependencyDAO, HangarDao<ProjectVersionDependenciesDAO> projectVersionDependencyDAO, HangarDao<PlatformVersionDAO> platformVersionDAO, HangarDao<ProjectVersionsDAO> projectVersionDAO, ProjectFiles projectFiles, PluginDataService pluginDataService, ChannelService channelService, ProjectVisibilityService projectVisibilityService, RecommendedVersionService recommendedVersionService, ProjectService projectService, NotificationService notificationService, VersionService versionService, PlatformService platformService, UsersApiService usersApiService) {
        this.projectVersionPlatformDependenciesDAO = projectVersionPlatformDependencyDAO.get();
        this.projectVersionDependenciesDAO = projectVersionDependencyDAO.get();
        this.platformVersionDAO = platformVersionDAO.get();
        this.projectVersionsDAO = projectVersionDAO.get();
        this.projectFiles = projectFiles;
        this.pluginDataService = pluginDataService;
        this.channelService = channelService;
        this.projectVisibilityService = projectVisibilityService;
        this.recommendedVersionService = recommendedVersionService;
        this.projectService = projectService;
        this.notificationService = notificationService;
        this.versionService = versionService;
        this.platformService = platformService;
        this.usersApiService = usersApiService;
    }

    public PendingVersion createPendingVersion(long projectId, MultipartFile file) {
        ProjectTable projectTable = projectService.getProjectTable(projectId);
        assert projectTable != null;
        String pluginFileName = file.getOriginalFilename();
        if (pluginFileName == null || (!pluginFileName.endsWith(".zip") && !pluginFileName.endsWith(".jar"))) {
            throw new HangarApiException(HttpStatus.BAD_REQUEST, "version.new.error.fileExtension");
        }

        PluginFileWithData pluginDataFile;
        try {
            Path tmpDir = projectFiles.getTempDir(getHangarPrincipal().getName());
            if (!Files.isDirectory(tmpDir)) {
                Files.createDirectories(tmpDir);
            }

            Path tmpPluginFile = tmpDir.resolve(pluginFileName);
            file.transferTo(tmpPluginFile);
            pluginDataFile = pluginDataService.loadMeta(tmpPluginFile, getHangarPrincipal().getUserId());
        } catch (IOException e) {
            logger.error("Error while uploading {} for {}", pluginFileName, getHangarPrincipal().getName(), e);
            throw new HangarApiException(HttpStatus.BAD_REQUEST, "version.new.error.unexpected");
        }

        String versionString = StringUtils.slugify(pluginDataFile.getData().getVersion());
        if (!hangarConfig.projects.getVersionNameMatcher().test(versionString)) {
            throw new HangarApiException(HttpStatus.BAD_REQUEST, "version.new.error.invalidVersionString");
        }

        if (exists(projectId, versionString, pluginDataFile.getData().getPlatformDependencies().keySet())) {
            throw new HangarApiException(HttpStatus.BAD_REQUEST, "version.new.error.duplicateNameAndPlatform");
        }

        ProjectChannelTable projectChannelTable = channelService.getFirstChannel(projectId);
        PendingVersion pendingVersion = new PendingVersion(
                StringUtils.slugify(pluginDataFile.getData().getVersion()),
                pluginDataFile.getData().getDependencies(),
                pluginDataFile.getData().getPlatformDependencies(),
                pluginDataFile.getData().getDescription(),
                new FileInfo(pluginDataFile.getPath().getFileName().toString(), pluginDataFile.getPath().toFile().length(), pluginDataFile.getMd5()),
                projectChannelTable,
                projectTable.isForumSync()
        );

        if (projectVersionsDAO.getProjectVersionTable(projectId, pluginDataFile.getMd5(), pendingVersion.getVersionString()) != null && hangarConfig.projects.isFileValidate()) {
            throw new HangarApiException(HttpStatus.BAD_REQUEST, "version.new.error.duplicate");
        }
        return pendingVersion;
    }

    public PendingVersion createPendingVersion(long projectId, String url) {
        ProjectTable projectTable = projectService.getProjectTable(projectId);
        assert projectTable != null;
        ProjectChannelTable projectChannelTable = channelService.getFirstChannel(projectId);
        return new PendingVersion(url, projectChannelTable, projectTable.isForumSync());
    }

    public void publishPendingVersion(long projectId, final PendingVersion pendingVersion) {
        final ProjectTable projectTable = projectService.getProjectTable(projectId);
        assert projectTable != null;
        Path tmpVersionJar = null;
        if (pendingVersion.isFile()) { // verify file
            tmpVersionJar = projectFiles.getTempDir(getHangarPrincipal().getName()).resolve(pendingVersion.getFileInfo().getName());
            try {
                if (Files.notExists(tmpVersionJar)) {
                    throw new HangarApiException(HttpStatus.BAD_REQUEST, "version.new.error.noFile");
                } else if (tmpVersionJar.toFile().length() != pendingVersion.getFileInfo().getSizeBytes()) {
                    throw new HangarApiException(HttpStatus.BAD_REQUEST, "version.new.error.mismatchedFileSize");
                } else if (!Objects.equals(CryptoUtils.md5ToHex(Files.readAllBytes(tmpVersionJar)), pendingVersion.getFileInfo().getMd5Hash())) {
                    throw new HangarApiException(HttpStatus.BAD_REQUEST, "version.new.error.hashMismatch");
                }
            } catch (IOException e) {
                logger.error("Could not publish version for {}", getHangarPrincipal().getName(), e);
            }
        } else if (exists(projectId, pendingVersion.getVersionString(), pendingVersion.getPlatformDependencies().keySet())) {
            throw new HangarApiException(HttpStatus.BAD_REQUEST, "version.new.error.duplicateNameAndPlatform");
        }

        if (pendingVersion.getPlatformDependencies().entrySet().stream().anyMatch(entry -> !platformService.getVersionsForPlatform(entry.getKey()).containsAll(entry.getValue()))) {
            throw new HangarApiException(HttpStatus.BAD_REQUEST, "version.new.error.invalidPlatformVersion");
        }

        ProjectVersionTable projectVersionTable = null;
        try {
            ProjectChannelTable projectChannelTable = channelService.getProjectChannel(projectId, pendingVersion.getChannelName(), pendingVersion.getChannelColor());
            if (projectChannelTable == null) {
                projectChannelTable = channelService.createProjectChannel(pendingVersion.getChannelName(), pendingVersion.getChannelColor(), projectId, pendingVersion.isChannelNonReviewed());
            }

            Long fileSize = null;
            String fileHash = null;
            String fileName = null;
            if (pendingVersion.getFileInfo() != null) {
                fileSize = pendingVersion.getFileInfo().getSizeBytes();
                fileHash = pendingVersion.getFileInfo().getMd5Hash();
                fileName = pendingVersion.getFileInfo().getName();
            }
            projectVersionTable = projectVersionsDAO.insert(new ProjectVersionTable(
                    pendingVersion.getVersionString(),
                    pendingVersion.getDescription(),
                    projectId,
                    projectChannelTable.getId(),
                    fileSize,
                    fileHash,
                    fileName,
                    getHangarPrincipal().getUserId(),
                    pendingVersion.isForumSync(),
                    pendingVersion.getExternalUrl()
            ));

            List<ProjectVersionTagTable> projectVersionTagTables = new ArrayList<>();
            List<ProjectVersionPlatformDependencyTable> platformDependencyTables = new ArrayList<>();
            for (var entry : pendingVersion.getPlatformDependencies().entrySet()) {
                projectVersionTagTables.add(new ProjectVersionTagTable(projectVersionTable.getId(), entry.getKey().getName(), entry.getValue(), entry.getKey().getTagColor()));
                for (String version : entry.getValue()) {
                    PlatformVersionTable platformVersionTable = platformVersionDAO.getByPlatformAndVersion(entry.getKey(), version);
                    platformDependencyTables.add(new ProjectVersionPlatformDependencyTable(projectVersionTable.getId(), platformVersionTable.getId()));
                }
            }
            projectVersionsDAO.insertTags(projectVersionTagTables);
            projectVersionPlatformDependenciesDAO.insertAll(platformDependencyTables);

            List<ProjectVersionDependencyTable> pluginDependencyTables = new ArrayList<>();
            for (var platformListEntry : pendingVersion.getPluginDependencies().entrySet()) {
                for (PluginDependency pluginDependency : platformListEntry.getValue()) {
                    pluginDependencyTables.add(new ProjectVersionDependencyTable(projectVersionTable.getId(), platformListEntry.getKey(), pluginDependency.getName(), pluginDependency.isRequired(), pluginDependency.getProjectId(), pluginDependency.getExternalUrl()));
                }
            }
            projectVersionDependenciesDAO.insertAll(pluginDependencyTables);


            if (pendingVersion.isUnstable()) {
                versionService.addUnstableTag(projectVersionTable.getId());
            }

            notificationService.notifyUsersNewVersion(projectTable, projectVersionTable);

            if (tmpVersionJar != null) {
                for (Platform platform : pendingVersion.getPlatformDependencies().keySet()) {
                    if (pendingVersion.getPlatformDependencies().get(platform).size() < 1) continue;
                    Path newVersionJarPath = projectFiles.getVersionDir(projectTable.getOwnerName(), projectTable.getName(), pendingVersion.getVersionString()).resolve(platform.name()).resolve(tmpVersionJar.getFileName());
                    if (Files.notExists(newVersionJarPath)) {
                        Files.createDirectories(newVersionJarPath.getParent());
                    }

                    Files.copy(tmpVersionJar, newVersionJarPath, StandardCopyOption.REPLACE_EXISTING);
                    if (Files.notExists(newVersionJarPath)) {
                        throw new IOException("Didn't successfully move the jar");
                    }
                }
                Files.deleteIfExists(tmpVersionJar);
            }

            if (projectTable.getVisibility() == Visibility.NEW) {
                projectVisibilityService.changeVisibility(projectTable, Visibility.PUBLIC, "First version");
                // TODO add forum job
            }

            if (pendingVersion.isRecommended()) {
                for (Platform platform : pendingVersion.getPlatformDependencies().keySet()) {
                    recommendedVersionService.setRecommendedVersion(projectId, projectVersionTable.getId(), platform);
                }
            }

            userActionLogService.version(LoggedActionType.VERSION_UPLOADED.with(VersionContext.of(projectId, projectVersionTable.getId())), "published", "");

            projectService.refreshHomeProjects();
            usersApiService.clearAuthorsCache();
        } catch (IOException e) {
            logger.error("Unable to create version {} for {}", pendingVersion.getVersionString(), getHangarPrincipal().getName(), e);
            projectVersionsDAO.delete(projectVersionTable);
            throw new HangarApiException(HttpStatus.BAD_REQUEST, "version.new.error.fileIOError");
        } catch (Throwable throwable) {
            logger.error("Unable to create version {} for {}", pendingVersion.getVersionString(), getHangarPrincipal().getName(), throwable);
            if (projectVersionTable != null) {
                projectVersionsDAO.delete(projectVersionTable);
            }
            throw new HangarApiException(HttpStatus.BAD_REQUEST, "version.new.error.unknown");
        }
    }

    private boolean exists(long projectId, String versionString, Collection<Platform> platforms) {
        List<PlatformVersionTable> platformTables = platformVersionDAO.getPlatformsForVersionString(projectId, versionString);
        return platformTables.stream().anyMatch(pt -> platforms.contains(pt.getPlatform()));
    }
}